"""Context-building: load pair-level signals + assemble compacted markdown context.

Black box:
  input — pair_idx + ranker scores + k_drop + topic_decay.
  output — markdown string with the source pair removed and remaining session
          pairs ranked by `scores[pid] * topic_decay**|topic_distance|`.
  entry — loaders are flat npz/jsonl readers (load_pairs / load_density /
          load_importance / load_topic_map). `build_compacted_context` is the
          assembly head. Public package version drops some substrate-only
          helpers (chain_neighbors, segment_pair_idxs) — those live in the
          maintainer-private substrate copy of this module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ._constants import (
    BASELINE_RANDOM,
    BASELINE_RECENCY,
    DENSITY,
    IMPORTANCE,
    PAIRS,
    TOPIC_SEGMENTS,
)
from weighted_compact import config as _wc_config


def _check_schema_ver(npz, path: Path, expected: int, rebuild_cmd: str) -> None:
    """Guard against silent KeyError / shape-mismatch on stale npz files.

    Backward-compat: files written before the schema_ver field exists are
    treated as version 0 (the implicit pre-fingerprint era) and accepted
    silently. The first version bump after rollout will then trigger a
    loud, fix-directive message instead of a downstream traceback.
    """
    files = getattr(npz, 'files', None)
    if files is None or 'schema_ver' not in files:
        return  # legacy file → treat as version 0, accept
    try:
        got = int(npz['schema_ver'][0])
    except (KeyError, IndexError, ValueError, TypeError):
        return  # unreadable field — be permissive, don't punish the loader
    if got != expected:
        raise RuntimeError(
            f"{path}: schema_ver {got} != current {expected}. "
            f"Rebuild with: {rebuild_cmd}"
        )


def _safe_npz_load(path: Path, rebuild_cmd: str, *, allow_pickle: bool = True):
    """Wrap np.load with a structured error for corrupted / unreadable files.

    Bare np.load on a truncated or non-npz file raises ValueError / EOFError
    / zipfile.BadZipFile, all with messages that look like internals leakage.
    Catch those at the loader edge and re-raise as RuntimeError carrying the
    absolute path plus the exact rebuild command. Programmer bugs (KeyError,
    indexing) intentionally propagate — only environmental corruption is
    wrapped.
    """
    import zipfile
    try:
        return np.load(path, allow_pickle=allow_pickle)
    except (ValueError, OSError, EOFError, zipfile.BadZipFile) as exc:
        raise RuntimeError(
            f"{path}: file is corrupted or not a valid .npz ({type(exc).__name__}: {exc}). "
            f"Rebuild with: {rebuild_cmd}"
        ) from exc


def load_pairs():
    """Load pairs.jsonl, return list of dicts with added 'pair_idx' = enumerate index.

    Tolerant to corrupted lines: a single bad JSON line is logged-as-skip,
    not raised, because the substrate is appended-to over months and the
    eval loop should survive one partial-write.
    """
    pairs = []
    with open(PAIRS, encoding='utf-8') as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            r['pair_idx'] = i
            pairs.append(r)
    return pairs


def load_density():
    """Load features_density.npz → dict pair_idx → mean-of-16-features score."""
    npz = _safe_npz_load(DENSITY, "weighted-compact bootstrap && python -m weighted_compact.density_features", allow_pickle=False)
    arr = npz['density']
    pair_indices = npz['pair_indices']
    scores = arr.mean(axis=1)
    return {int(pair_indices[i]): float(scores[i]) for i in range(len(scores))}


def load_importance():
    """Load importance.npz (Phase 4C mixture) → dict pair_idx → importance.

    Fallback to load_density() if importance.npz missing.
    """
    if not IMPORTANCE.exists():
        return load_density()
    npz = _safe_npz_load(IMPORTANCE, "weighted-compact importance")
    from weighted_compact.importance import SCHEMA_VER as _IMPORTANCE_SCHEMA
    _check_schema_ver(npz, IMPORTANCE, _IMPORTANCE_SCHEMA,
                      "weighted-compact importance")
    return {int(npz['pair_indices'][i]): float(npz['importance'][i])
            for i in range(len(npz['importance']))}


def load_topic_map():
    """Load topic_segments.npz → dict pair_idx → topic_id. Empty if missing."""
    if not TOPIC_SEGMENTS.exists():
        return {}
    npz = _safe_npz_load(TOPIC_SEGMENTS, "python -m weighted_compact.topic_segments")
    return {int(npz['pair_indices'][i]): int(npz['topic_id'][i])
            for i in range(len(npz['pair_indices']))}


def _load_baseline_npz(path, ranker_name):
    """Shared loader for baseline ranker npz files (same schema as importance.npz)."""
    if not path.exists():
        raise FileNotFoundError(
            f'{path} not found — run `weighted-compact baseline build '
            f'--ranker {ranker_name}` first',
        )
    npz = _safe_npz_load(
        path, f"weighted-compact baseline build --ranker {ranker_name}",
    )
    # Lazy import: avoid pulling baseline modules at recon_qa import time.
    if ranker_name == 'random':
        from weighted_compact.baselines.random_ranker import SCHEMA_VER as _SCHEMA
    elif ranker_name == 'recency':
        from weighted_compact.baselines.recency_ranker import SCHEMA_VER as _SCHEMA
    else:
        _SCHEMA = 1  # unknown family — be permissive
    _check_schema_ver(
        npz, path, _SCHEMA,
        f"weighted-compact baseline build --ranker {ranker_name}",
    )
    return {int(npz['pair_indices'][i]): float(npz['importance'][i])
            for i in range(len(npz['importance']))}


def load_baseline_random():
    """Load baseline_random.npz → dict pair_idx → score ∈ [0, 1]."""
    return _load_baseline_npz(BASELINE_RANDOM, 'random')


def load_baseline_recency():
    """Load baseline_recency.npz → dict pair_idx → score ∈ [0, 1]."""
    return _load_baseline_npz(BASELINE_RECENCY, 'recency')


def load_rem_decay():
    """Load rem_decay.npz → dict pair_idx → multiplier ∈ (0, 1].

    Returns an empty dict if the REM pass has never been run. Callers should
    treat an empty map as "no decay applied" — `build_compacted_context`
    handles this transparently when `rem_decay_map` is None or empty.
    """
    path = _wc_config.rem_decay_path()
    if not path.exists():
        return {}
    npz = _safe_npz_load(path, "weighted-compact rem-pass")
    from weighted_compact.rem_decay import SCHEMA_VER as _REM_SCHEMA
    _check_schema_ver(npz, path, _REM_SCHEMA, "weighted-compact rem-pass")
    return {int(npz['pair_indices'][i]): float(npz['importance'][i])
            for i in range(len(npz['importance']))}


def build_compacted_context(source_pair_idx, pairs, scoring, k_drop=0.5,
                            topic_decay=0.5, topic_map=None, query=None,
                            rem_decay_map=None):
    """Assemble markdown context for a session, hiding source_pair (ground truth).

    `scoring` is one of:
      - dict[pair_idx, float] — pre-computed static ranking (importance,
        density, random, recency baselines)
      - callable(query: str) -> dict[pair_idx, float] — query-aware ranker
        (cosine, BM25) that recomputes per-pair scores given the question

    For callable rankers, `query` must be provided.

    Topic-shift drop (Phase 4E, no classifier — pure embedding cohesion):
      topic_map: dict pair_idx → topic_id.
      For each candidate, distance d = |topic_candidate - topic_source|.
      effective_score = scores[pid] * topic_decay^d.
      Pass topic_map=None (or topic_decay=1.0) to disable.

    REM-decay multiplier (wall-clock recency, Phase 4F):
      rem_decay_map: dict pair_idx → factor ∈ (0, 1] produced by the nightly
      `weighted-compact rem-pass`. Multiplied into the score after the topic
      term. Empty / None → no decay applied. See `weighted_compact.rem_decay`.
    """
    if callable(scoring):
        if query is None:
            raise ValueError(
                'callable scoring (query-aware ranker) requires query argument',
            )
        scores = scoring(query)
    else:
        scores = scoring

    source_pair = pairs[source_pair_idx]
    sess = source_pair['session_id']
    session_pairs = [
        p for p in pairs
        if p['session_id'] == sess and p['pair_idx'] != source_pair_idx
    ]
    if not session_pairs:
        return ''

    rem = rem_decay_map or {}

    if topic_map and topic_decay < 1.0:
        t_source = topic_map.get(source_pair_idx, 0)

        def eff(p):
            t = topic_map.get(p['pair_idx'], 0)
            d = abs(t - t_source)
            base = scores.get(p['pair_idx'], 0.0) * (topic_decay ** d)
            return base * rem.get(p['pair_idx'], 1.0)
        ranked = sorted(session_pairs, key=eff, reverse=True)
    else:
        ranked = sorted(
            session_pairs,
            key=lambda p: scores.get(p['pair_idx'], 0.0) * rem.get(p['pair_idx'], 1.0),
            reverse=True,
        )

    keep_n = max(1, int(len(ranked) * (1 - k_drop)))
    kept = ranked[:keep_n]
    kept.sort(key=lambda p: p['pair_idx'])

    chunks = [
        f"PREMISE: {p['premise_text']}\n\nCORRECTION: {p['correction_text']}"
        for p in kept
    ]
    return '\n\n---\n\n'.join(chunks)


def build_compacted_context_with_meta(
    source_pair_idx, pairs, scoring, k_drop=0.5,
    topic_decay=0.5, topic_map=None, query=None,
    rem_decay_map=None,
    importance_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Same as ``build_compacted_context`` but also returns a budget-transparency dict.

    Returns
    -------
    markdown : str
        Identical output to ``build_compacted_context``.
    meta : dict
        Token-budget readout with these keys:

        pairs_total          — session pairs available (excluding source_pair_idx)
        pairs_kept           — pairs present in the returned markdown
        pairs_dropped        — pairs_total − pairs_kept
        input_chars          — sum of len(premise_text)+len(correction_text) for
                               every session pair (excluding source), i.e. the
                               cost of including everything unfiltered
        output_chars         — len(markdown)
        chars_saved          — input_chars − output_chars
        tokens_estimate      — output_chars // 4  (cheap heuristic: ~4 chars/token
                               for English prose; not a real tokenizer count)
        tokens_saved_estimate — chars_saved // 4  (same heuristic, same caveat)
        compaction_ratio     — output_chars / input_chars, or 0.0 if input_chars == 0
        signals_top3         — list of up-to-3 (signal_name, mean_contribution) tuples,
                               descending. Computed as mean(components[i] * weights[i])
                               over kept pairs. Empty list if importance.npz is missing
                               or kept pair indices are not all present in it.
        ranker               — "callable_query_aware" if scoring is callable,
                               else "static_dict"

    The ``// 4`` token estimates are intentionally rough. They exist to give
    consumers a fast, dependency-free cost signal — not a billing-accurate count.
    Use a real tokenizer (e.g. tiktoken) if you need precision.

    Signal breakdown degrades silently: if ``importance_path`` is missing the
    file, or if any kept pair is absent from the npz index, ``signals_top3``
    returns ``[]`` without raising.
    """
    markdown = build_compacted_context(
        source_pair_idx, pairs, scoring,
        k_drop=k_drop, topic_decay=topic_decay, topic_map=topic_map,
        query=query, rem_decay_map=rem_decay_map,
    )

    source_pair = pairs[source_pair_idx]
    sess = source_pair['session_id']
    session_pairs = [
        p for p in pairs
        if p['session_id'] == sess and p['pair_idx'] != source_pair_idx
    ]

    pairs_total = len(session_pairs)
    input_chars = sum(
        len(p.get('premise_text', '')) + len(p.get('correction_text', ''))
        for p in session_pairs
    )
    output_chars = len(markdown)
    chars_saved = input_chars - output_chars

    # Reconstruct kept set to get pairs_kept count and signal breakdown.
    # We mirror the ranking logic from build_compacted_context.
    if callable(scoring):
        scores = scoring(query)
    else:
        scores = scoring

    rem = rem_decay_map or {}

    if topic_map and topic_decay < 1.0:
        t_source = topic_map.get(source_pair_idx, 0)

        def _eff(p):
            t = topic_map.get(p['pair_idx'], 0)
            d = abs(t - t_source)
            base = scores.get(p['pair_idx'], 0.0) * (topic_decay ** d)
            return base * rem.get(p['pair_idx'], 1.0)
        ranked = sorted(session_pairs, key=_eff, reverse=True)
    else:
        ranked = sorted(
            session_pairs,
            key=lambda p: scores.get(p['pair_idx'], 0.0) * rem.get(p['pair_idx'], 1.0),
            reverse=True,
        )

    keep_n = max(1, int(len(ranked) * (1 - k_drop))) if ranked else 0
    kept = ranked[:keep_n]
    pairs_kept = len(kept)

    # Signal breakdown from importance.npz
    signals_top3: list[tuple[str, float]] = []
    if importance_path is None:
        from weighted_compact import config as _wc_config
        importance_path = _wc_config.importance_path()

    if kept and importance_path.exists():
        try:
            npz = np.load(importance_path, allow_pickle=True)
            npz_indices = {int(npz['pair_indices'][i]): i
                           for i in range(len(npz['pair_indices']))}
            components = npz['components']   # (N, 7)
            weights = npz['weights']          # (7,)
            component_names = [str(n) for n in npz['component_names']]

            rows = []
            for p in kept:
                row_idx = npz_indices.get(p['pair_idx'])
                if row_idx is None:
                    rows = []
                    break
                rows.append(row_idx)

            if rows:
                kept_components = components[rows]          # (kept_n, 7)
                contributions = kept_components * weights   # (kept_n, 7) — element-wise
                mean_contrib = contributions.mean(axis=0)   # (7,)
                ranked_signals = sorted(
                    zip(component_names, mean_contrib.tolist()),
                    key=lambda x: x[1],
                    reverse=True,
                )
                signals_top3 = [(name, float(val)) for name, val in ranked_signals[:3]]
        except Exception:  # noqa: BLE001 — silent degradation intentional
            signals_top3 = []

    meta: dict[str, Any] = {
        'pairs_total': pairs_total,
        'pairs_kept': pairs_kept,
        'pairs_dropped': pairs_total - pairs_kept,
        'input_chars': input_chars,
        'output_chars': output_chars,
        'chars_saved': chars_saved,
        'tokens_estimate': output_chars // 4,
        'tokens_saved_estimate': chars_saved // 4,
        'compaction_ratio': output_chars / input_chars if input_chars > 0 else 0.0,
        'signals_top3': signals_top3,
        'ranker': 'callable_query_aware' if callable(scoring) else 'static_dict',
    }
    return markdown, meta
