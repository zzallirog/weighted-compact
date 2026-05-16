#!/usr/bin/env python3
"""Phase 4B — misstep stumble score per pair correction.

Trains a logistic regression on misstep's user-turn embeddings + stumble
labels (the same Run 3 baseline that gets AUC ~0.659 in misstep), then
scores each weighted-compact pair's correction embedding (third axis of
features.npz, layout [prev_assistant, premise, correction]).

Importance hypothesis (per TASKS.md §"Phase 2.5 weak supervision"):
  important pair ≈ user STOPPED stumbling on this correction
  → LOW stumble probability at correction = HIGH load-bearing weight

Output features_misstep.npz:
  stumble_prob : (N,)  P(stumble) ∈ [0,1] from logreg
  importance   : (N,)  1 - stumble_prob, clipped + rescaled
  pair_indices : (N,)
  meta         : auc on held-out + train size

Must run under misstep's venv (has duckdb + sklearn):
  ~/work/misstep/.venv/bin/python misstep_score.py
"""
import json
from pathlib import Path

import numpy as np
import duckdb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

import os

from weighted_compact import config

WC_ROOT = config.workdir()
WC_FEATURES = config.features_path()
OUT = config.features_misstep_path()

# misstep is a sibling project at https://github.com/zzallirog/misstep that
# trains a personal stumble predictor. Its substrate path can be overridden
# with $MISSTEP_DATA; otherwise we look at the conventional location.
MS_ROOT = Path(
    os.environ.get("MISSTEP_DATA")
    or (Path.home() / "work" / "misstep")
).expanduser()

MS_EMBED = MS_ROOT / 'data' / 'embeddings' / 'user_e5s.npz'
MS_DB    = MS_ROOT / 'data' / 'corpus.duckdb'


def load_misstep_training():
    z = np.load(MS_EMBED, allow_pickle=True)
    X = z['X'].astype(np.float32)
    turn_ids = z['turn_ids']
    session_ids = z['session_ids']
    con = duckdb.connect(str(MS_DB), read_only=True)
    rows = con.execute(
        "SELECT DISTINCT turn_id FROM stumble_events WHERE role='user'"
    ).fetchall()
    con.close()
    stumble = {r[0] for r in rows}
    y = np.array([1 if int(t) in stumble else 0 for t in turn_ids], dtype=np.int8)
    return X, y, session_ids


def train_logreg(X, y, session_ids):
    """Session-split (no leakage); train logreg; report held-out AUC."""
    rng = np.random.default_rng(0)
    uniq = np.unique(session_ids)
    rng.shuffle(uniq)
    cut = int(len(uniq) * 0.8)
    train_sess = set(uniq[:cut])
    train_mask = np.array([s in train_sess for s in session_ids])
    test_mask  = ~train_mask
    clf = LogisticRegression(
        C=1.0, class_weight='balanced',
        max_iter=200, solver='liblinear',
    )
    clf.fit(X[train_mask], y[train_mask])
    test_scores = clf.predict_proba(X[test_mask])[:, 1]
    auc = float('nan')
    if y[test_mask].sum() > 0:
        auc = float(roc_auc_score(y[test_mask], test_scores))
    return clf, {
        'auc_held_out': auc,
        'n_train': int(train_mask.sum()),
        'n_test':  int(test_mask.sum()),
        'n_pos_train': int(y[train_mask].sum()),
        'n_pos_test':  int(y[test_mask].sum()),
    }


def main():
    print('Loading misstep training set ...')
    X, y, session_ids = load_misstep_training()
    print(f'  X={X.shape}  pos={int(y.sum())}/{len(y)} '
          f'({100*y.mean():.2f}%)')

    print('Training logreg (session-split) ...')
    clf, meta = train_logreg(X, y, session_ids)
    print(f'  held-out AUC: {meta["auc_held_out"]:.3f}  '
          f'(train n={meta["n_train"]}, pos={meta["n_pos_train"]})')

    print('Refitting on full corpus for scoring ...')
    full_clf = LogisticRegression(
        C=1.0, class_weight='balanced',
        max_iter=200, solver='liblinear',
    )
    full_clf.fit(X, y)

    print('Scoring weighted-compact pair corrections ...')
    feats = np.load(WC_FEATURES, allow_pickle=True)
    windows = feats['windows']             # (N, 3, 384)
    pair_indices = feats['pair_indices']
    correction_vecs = windows[:, 2, :].astype(np.float32)  # (N, 384) — third axis = correction

    stumble_prob = full_clf.predict_proba(correction_vecs)[:, 1]
    importance = 1.0 - stumble_prob

    # Normalize importance to [0, 1] via percentile rank (robust to logreg scale)
    from scipy.stats import rankdata
    importance_rank = (rankdata(importance, method='average') - 1) / max(1, len(importance) - 1)

    np.savez(
        OUT,
        stumble_prob=stumble_prob.astype(np.float32),
        importance=importance.astype(np.float32),
        importance_rank=importance_rank.astype(np.float32),
        pair_indices=pair_indices.astype(np.int32),
        meta=np.array([json.dumps(meta)], dtype=object),
    )

    print(f'\n--- Summary ---')
    print(f'Output: {OUT}')
    print(f'Scored: {len(pair_indices)} pairs')
    print(f'stumble_prob: min={stumble_prob.min():.3f} max={stumble_prob.max():.3f} '
          f'mean={stumble_prob.mean():.3f}')
    print(f'importance:   min={importance.min():.3f} max={importance.max():.3f} '
          f'mean={importance.mean():.3f}')
    print(f'Distribution (percentile ranks): '
          f'10th={np.percentile(importance_rank, 10):.3f}, '
          f'50th={np.percentile(importance_rank, 50):.3f}, '
          f'90th={np.percentile(importance_rank, 90):.3f}')


if __name__ == '__main__':
    main()
