#!/usr/bin/env python3
"""Build active-learning queue for CAPTCHA-morning labeling loop.

Phase 2 producer: aggregates disagreement pairs + low-conf pairs + audit anchors
→ queue.jsonl ready for label_pairs.py --queue.

Usage: python3 build_queue.py
"""
import json
import random

from weighted_compact import config

WORKDIR = config.workdir()
DISAGREEMENT = config.disagreement_queue_path()
LABELS = config.labels_path()
PAIRS = config.pairs_path()
QUEUE = config.queue_path()

DAILY_RATE = 10


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    # --- Load inputs ---
    disagreements = load_jsonl(DISAGREEMENT)
    dis_idx = {d['pair_idx']: d for d in disagreements}

    labels = load_jsonl(LABELS)
    # Last label wins per pair_idx (dedup labels.jsonl)
    label_map = {}
    for lb in labels:
        label_map[lb['pair_idx']] = lb

    pairs = load_jsonl(PAIRS)
    pair_map = {i: p for i, p in enumerate(pairs)}

    # --- Category 1: disagreement entries ---
    queue_dis = []
    for d in disagreements:
        idx = d['pair_idx']
        lb = label_map.get(idx, {})
        queue_dis.append({
            'pair_idx': idx,
            'source': 'bootstrap_disagreement',
            'current_label': lb.get('label'),
            'predicted_tier': d['predicted_tier'],
            'session_id': lb.get('session_id') or pair_map.get(idx, {}).get('session_id'),
        })

    # --- Category 2: low-conf claude_auto (not already in disagreement) ---
    queue_low = []
    for idx, lb in label_map.items():
        if lb.get('labeled_by') == 'claude_auto' and lb.get('confidence') == 'low':
            if idx not in dis_idx:
                queue_low.append({
                    'pair_idx': idx,
                    'source': 'low_confidence',
                    'current_label': lb.get('label'),
                    'predicted_tier': None,
                    'session_id': lb.get('session_id'),
                })

    # --- Category 3: audit anchors (5% of total, min 3) ---
    # Pool: high-conf claude_auto entries not in disagreement or low-conf sets
    low_idx = {e['pair_idx'] for e in queue_low}
    anchor_pool = [
        lb for idx, lb in label_map.items()
        if lb.get('labeled_by') == 'claude_auto'
        and lb.get('confidence') == 'high'
        and idx not in dis_idx
        and idx not in low_idx
    ]

    pre_audit_size = len(queue_dis) + len(queue_low)
    n_anchors = max(3, int((pre_audit_size + 3) * 0.05 / (1 - 0.05)))  # solve for 5% of total

    random.seed(42)
    anchor_sample = random.sample(anchor_pool, min(n_anchors, len(anchor_pool)))
    queue_anchors = []
    for lb in anchor_sample:
        queue_anchors.append({
            'pair_idx': lb['pair_idx'],
            'source': 'audit_anchor',
            'current_label': lb.get('label'),
            'predicted_tier': None,
            'session_id': lb.get('session_id'),
        })

    # --- Deduplicate: disagreement > low_conf > audit ---
    seen = set()
    final = []
    for entry in queue_dis + queue_low + queue_anchors:
        if entry['pair_idx'] not in seen:
            seen.add(entry['pair_idx'])
            final.append(entry)

    # --- Shuffle ---
    random.seed(42)
    random.shuffle(final)

    # --- Save ---
    with open(QUEUE, 'w') as f:
        for entry in final:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    # --- Summary ---
    by_source = {}
    for e in final:
        by_source[e['source']] = by_source.get(e['source'], 0) + 1

    days = -(-len(final) // DAILY_RATE)  # ceil division
    print(f"Queue built → {QUEUE}")
    print(f"Total: {len(final)} entries")
    print(f"By source:")
    for src in ('bootstrap_disagreement', 'low_confidence', 'audit_anchor'):
        cnt = by_source.get(src, 0)
        pct = cnt / len(final) * 100 if final else 0
        print(f"  {src:<28} {cnt:4d}  ({pct:.1f}%)")
    print(f"Estimated days to clear: ~{days}d  (@{DAILY_RATE}/day)")


if __name__ == '__main__':
    main()
