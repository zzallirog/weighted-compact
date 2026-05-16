#!/usr/bin/env python3
"""Phase 4E — per-session topic segmentation via embedding cohesion.

No classifier. Pure geometry on e5 correction embeddings (3rd axis of
features.npz windows). Idea (TextTiling-style):

  for each pair position i within a session-ordered sequence,
    left  = mean(embed[i-W : i])
    right = mean(embed[i : i+W])
    cohesion(i) = cos(left, right)

  Locations where cohesion drops sharply below local rolling baseline are
  marked as topic boundaries. Each pair gets a topic_id by counting how
  many boundaries precede it within its session.

Output topic_segments.npz:
  pair_indices : (N,) int32                    — aligned with features.npz order
  topic_id     : (N,) int32                    — incremental per-session topic counter
  session_pos  : (N,) int32                    — position of pair within its session (0-indexed)
  cohesion     : (N,) float32                  — local cohesion score (1 = same topic, 0 = unrelated)
  is_boundary  : (N,) int8                     — 1 if this pair starts a new topic chunk
  meta         : json (W, drop_quantile, etc.)

Usage:
    python3 topic_segments.py
"""
import json
from collections import defaultdict

import numpy as np

from weighted_compact import config

FEATURES = config.features_path()
PAIRS = config.pairs_path()
OUT = config.topic_segments_path()

# Hyperparameters — tunable, defaults conservative.
WINDOW = 2                  # turns on each side of the position
DROP_QUANTILE = 0.20        # boundary fires when cohesion ≤ this quantile within the session
MIN_SESSION_PAIRS = 4       # sessions with <4 pairs: single topic, no segmentation


def cos_sim(a, b):
    na = np.linalg.norm(a) + 1e-9
    nb = np.linalg.norm(b) + 1e-9
    return float(np.dot(a, b) / (na * nb))


def segment_session(pair_indices_in_session, corr_vecs):
    """Return (topic_ids, cohesions, boundaries) parallel arrays."""
    n = len(pair_indices_in_session)
    cohesions = np.ones(n, dtype=np.float32)
    if n < MIN_SESSION_PAIRS:
        return np.zeros(n, dtype=np.int32), cohesions, np.zeros(n, dtype=np.int8)

    embs = np.array([corr_vecs[i] for i in pair_indices_in_session])
    for i in range(n):
        lo = max(0, i - WINDOW)
        hi = min(n, i + WINDOW)
        if i == 0 or i == n - 1:
            cohesions[i] = 1.0  # edges = no boundary
            continue
        left  = embs[lo:i].mean(axis=0)
        right = embs[i:hi].mean(axis=0)
        cohesions[i] = cos_sim(left, right)

    # Threshold = local quantile within session
    threshold = float(np.quantile(cohesions, DROP_QUANTILE))
    # Boundary requires both: below threshold AND local minimum (1-of-3 valley)
    boundaries = np.zeros(n, dtype=np.int8)
    for i in range(2, n - 2):
        if (cohesions[i] <= threshold
            and cohesions[i] <= cohesions[i-1]
            and cohesions[i] <= cohesions[i+1]):
            boundaries[i] = 1

    topic_ids = np.cumsum(boundaries, dtype=np.int32)
    return topic_ids, cohesions, boundaries


def main():
    feats = np.load(FEATURES, allow_pickle=True)
    windows = feats['windows']        # (N, 3, 384)
    pair_indices = feats['pair_indices']  # (N,)
    corr_vecs = windows[:, 2, :]      # correction embedding

    # Load pair → session map
    sessions_for_pair = {}
    with open(PAIRS, encoding='utf-8') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            sessions_for_pair[idx] = r['session_id']

    # Map: features.npz row → pair_idx
    row_for_pair = {int(pair_indices[r]): r for r in range(len(pair_indices))}

    # Group pair_idx by session, preserve pair_idx order (~chronological)
    session_pairs = defaultdict(list)
    for pid in sorted(sessions_for_pair):
        if pid in row_for_pair:
            session_pairs[sessions_for_pair[pid]].append(pid)

    out_topic_id    = np.zeros(len(pair_indices), dtype=np.int32)
    out_session_pos = np.zeros(len(pair_indices), dtype=np.int32)
    out_cohesion    = np.ones(len(pair_indices), dtype=np.float32)
    out_boundary    = np.zeros(len(pair_indices), dtype=np.int8)

    total_boundaries = 0
    sessions_with_boundary = 0
    multi_topic_sessions = 0

    for sess, pair_list in session_pairs.items():
        rows = [row_for_pair[p] for p in pair_list]
        # Build temporary corr_vecs slice indexed by position in session
        local_vecs = {i: corr_vecs[rows[i]] for i in range(len(rows))}
        topic_ids, cohesions, boundaries = segment_session(
            list(range(len(rows))), local_vecs
        )
        for pos, (r, t, c, b) in enumerate(zip(rows, topic_ids, cohesions, boundaries)):
            out_topic_id[r]    = int(t)
            out_session_pos[r] = pos
            out_cohesion[r]    = float(c)
            out_boundary[r]    = int(b)
        nb = int(boundaries.sum())
        if nb:
            sessions_with_boundary += 1
            total_boundaries += nb
        if topic_ids.max() > 0:
            multi_topic_sessions += 1

    meta = {
        'window': WINDOW,
        'drop_quantile': DROP_QUANTILE,
        'min_session_pairs': MIN_SESSION_PAIRS,
        'n_sessions': len(session_pairs),
        'n_sessions_with_boundary': sessions_with_boundary,
        'n_multi_topic_sessions': multi_topic_sessions,
        'total_boundaries': total_boundaries,
    }

    np.savez(
        OUT,
        pair_indices=pair_indices.astype(np.int32),
        topic_id=out_topic_id,
        session_pos=out_session_pos,
        cohesion=out_cohesion,
        is_boundary=out_boundary,
        meta=np.array([json.dumps(meta)], dtype=object),
    )

    print(f'Output: {OUT}')
    print(f'Sessions analyzed     : {meta["n_sessions"]}')
    print(f'Sessions with ≥1 bdry : {sessions_with_boundary}')
    print(f'Multi-topic sessions  : {multi_topic_sessions}')
    print(f'Total boundaries      : {total_boundaries}')
    print(f'Avg boundaries/sess   : {total_boundaries / max(1, len(session_pairs)):.2f}')
    print(f'Cohesion stats        : min={out_cohesion.min():.3f} '
          f'median={np.median(out_cohesion):.3f} mean={out_cohesion.mean():.3f}')
    print(f'Topic id distribution : '
          f'max={out_topic_id.max()} '
          f'unique_topics_total={len(set((sessions_for_pair[int(pi)], int(t)) for pi, t in zip(pair_indices, out_topic_id) if int(pi) in sessions_for_pair))}')


if __name__ == '__main__':
    main()
