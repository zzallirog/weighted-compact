#!/usr/bin/env python3
"""Incremental version of extract_pairs.py.

Reads existing pairs.jsonl, builds key set (session_id, correction_uuid),
runs same extraction logic over all session jsonl files in DIRS, filters
only-new pairs by key, and APPENDS them to pairs.jsonl. Existing pair_idx
positions are preserved — critical because labels.jsonl, features.npz, and
features_density.npz all index by positional pair_idx.

Usage: python3 extract_pairs_incremental.py
"""
import glob
import json
import os
from collections import Counter

from weighted_compact.extract_pairs import (
    DIRS,
    MIN_FILE_SIZE,
    OUT,
    build_pairs,
    process_file,
)


def load_existing_keys(path):
    if not os.path.exists(path):
        return set(), 0
    keys = set()
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            keys.add((obj["session_id"], obj["correction_uuid"]))
            count += 1
    return keys, count


def main():
    existing_keys, existing_count = load_existing_keys(OUT)
    print(f"Existing pairs: {existing_count}")

    files = []
    for d in DIRS:
        files.extend(glob.glob(os.path.join(d, "*.jsonl")))

    sessions_processed = 0
    new_pairs = []
    seen_new_keys = set()

    for path in sorted(files):
        if os.path.getsize(path) < MIN_FILE_SIZE:
            continue
        events = process_file(path)
        if not events:
            continue
        sessions_processed += 1
        for pair in build_pairs(events):
            key = (pair["session_id"], pair["correction_uuid"])
            if key in existing_keys or key in seen_new_keys:
                continue
            seen_new_keys.add(key)
            new_pairs.append(pair)

    if not new_pairs:
        print(f"Sessions scanned: {sessions_processed}")
        print("No new pairs.")
        return

    with open(OUT, "a", encoding="utf-8") as f:
        for pair in new_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    by_type = Counter(p["marker_type"] for p in new_pairs)
    by_tier = Counter(p["tier_hint"] for p in new_pairs)
    by_session = Counter(p["session_id"] for p in new_pairs)

    print(f"Sessions scanned    : {sessions_processed}")
    print(f"New pairs appended  : {len(new_pairs)}")
    print(f"Total pairs now     : {existing_count + len(new_pairs)}")
    print(f"By marker_type      : {dict(by_type)}")
    print(f"By tier_hint        : {dict(by_tier)}")
    print(f"Top-5 sessions      : {by_session.most_common(5)}")
    print(f"New idx range       : [{existing_count} .. {existing_count + len(new_pairs) - 1}]")


if __name__ == "__main__":
    main()
