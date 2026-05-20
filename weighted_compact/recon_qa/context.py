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
import json

import numpy as np

from ._constants import DENSITY, IMPORTANCE, PAIRS, TOPIC_SEGMENTS


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
    npz = np.load(DENSITY)
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
    npz = np.load(IMPORTANCE, allow_pickle=True)
    return {int(npz['pair_indices'][i]): float(npz['importance'][i])
            for i in range(len(npz['importance']))}


def load_topic_map():
    """Load topic_segments.npz → dict pair_idx → topic_id. Empty if missing."""
    if not TOPIC_SEGMENTS.exists():
        return {}
    npz = np.load(TOPIC_SEGMENTS, allow_pickle=True)
    return {int(npz['pair_indices'][i]): int(npz['topic_id'][i])
            for i in range(len(npz['pair_indices']))}


def build_compacted_context(source_pair_idx, pairs, scores, k_drop=0.5,
                            topic_decay=0.5, topic_map=None):
    """Assemble markdown context for a session, hiding source_pair (ground truth).

    `scores` is a dict pair_idx → ranking score (higher = preserve).

    Topic-shift drop (Phase 4E, no classifier — pure embedding cohesion):
      topic_map: dict pair_idx → topic_id.
      For each candidate, distance d = |topic_candidate - topic_source|.
      effective_score = scores[pid] * topic_decay^d.
      Pass topic_map=None (or topic_decay=1.0) to disable.
    """
    source_pair = pairs[source_pair_idx]
    sess = source_pair['session_id']
    session_pairs = [
        p for p in pairs
        if p['session_id'] == sess and p['pair_idx'] != source_pair_idx
    ]
    if not session_pairs:
        return ''

    if topic_map and topic_decay < 1.0:
        t_source = topic_map.get(source_pair_idx, 0)

        def eff(p):
            t = topic_map.get(p['pair_idx'], 0)
            d = abs(t - t_source)
            return scores.get(p['pair_idx'], 0.0) * (topic_decay ** d)
        ranked = sorted(session_pairs, key=eff, reverse=True)
    else:
        ranked = sorted(
            session_pairs,
            key=lambda p: scores.get(p['pair_idx'], 0.0),
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
