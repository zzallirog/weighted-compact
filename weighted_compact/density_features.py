#!/usr/bin/env python3
"""Content-density features per pair (no marker regex).

Per-pair signal: length, named-entity density, numbers/dates, code fences,
quoted strings, line count, unique-word ratio. Aligned with features.npz pair_indices.

Output: features_density.npz with keys {pair_indices, density, labels_3tier}.
"""
import json
import re

import numpy as np

from weighted_compact import config

WORKDIR = config.workdir()
PAIRS = config.pairs_path()
FEATURES = config.features_path()
OUT = config.features_density_path()

NAME_RE = re.compile(r'\b[A-ZА-ЯЁЇІЄҐ][a-zа-яёїієґ]{3,}\b')
NUM_RE = re.compile(r'\b\d{2,}\b|\b\d+[.,]\d+\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b')
QUOTE_RE = re.compile(r'[«"\'`][^«»"\'`]{4,}[»"\'`]')
CODE_FENCE_RE = re.compile(r'```|`[^`\n]+`|^\s{4,}\S', re.MULTILINE)
WORD_RE = re.compile(r"\b\w{2,}\b", re.UNICODE)

# Per-side feature names. To add a new feature: append a name here and append
# the corresponding numeric in `extract_density()`. Downstream sizing is
# derived from len(FEATURE_NAMES) at run time, so no other site needs editing.
FEATURE_NAMES = [
    'log_len', 'log_lines', 'log_names', 'log_nums',
    'log_quotes', 'log_code', 'uniq_ratio', 'log_words',
]


def extract_density(text):
    if not text:
        return np.zeros(len(FEATURE_NAMES), dtype=np.float32)
    length = len(text)
    lines = text.count('\n') + 1
    words = WORD_RE.findall(text.lower())
    unique_ratio = len(set(words)) / max(len(words), 1)
    return np.array([
        np.log1p(length),
        np.log1p(lines),
        np.log1p(len(NAME_RE.findall(text))),
        np.log1p(len(NUM_RE.findall(text))),
        np.log1p(len(QUOTE_RE.findall(text))),
        np.log1p(len(CODE_FENCE_RE.findall(text))),
        unique_ratio,
        np.log1p(len(words)),
    ], dtype=np.float32)


def main():
    pairs_by_idx = {}
    with open(PAIRS, encoding='utf-8') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                pairs_by_idx[idx] = json.loads(line)
            except json.JSONDecodeError:
                continue

    feats = np.load(FEATURES, allow_pickle=True)
    pair_indices = feats['pair_indices']
    labels_3tier = feats['labels_3tier']

    # Dimension derived once — 2 × D for (premise, correction) blocks.
    D = len(FEATURE_NAMES)
    density = np.zeros((len(pair_indices), 2 * D), dtype=np.float32)
    missing = 0
    for row, pidx in enumerate(pair_indices):
        p = pairs_by_idx.get(int(pidx))
        if p is None:
            missing += 1
            continue
        density[row, :D] = extract_density(p.get('premise_text', ''))
        density[row, D:] = extract_density(p.get('correction_text', ''))

    np.savez(OUT, density=density, pair_indices=pair_indices, labels_3tier=labels_3tier)

    print(f'Output: {OUT}')
    print(f'Density shape: {density.shape} ({D} features × 2 sides)')
    print(f'Missing pairs: {missing}')
    print('Per-feature mean (premise side):')
    for i, name in enumerate(FEATURE_NAMES):
        m = density[:, i].mean()
        by_label = [density[labels_3tier == t, i].mean() for t in (0, 1, 2)]
        print(f'  {name:14s} mean={m:.3f} | t0={by_label[0]:.3f} t1={by_label[1]:.3f} t2={by_label[2]:.3f}')


if __name__ == '__main__':
    main()
