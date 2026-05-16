#!/usr/bin/env python3
"""Incremental version of feature_extract.py.

Appends e5 embeddings for pairs in pairs.jsonl that don't yet have rows in
features.npz. Pair-without-label gets sentinel label=-1, labeled_by="pending",
confidence="fresh" — so downstream cluster mode includes them while filters that
care about labels can skip pending rows.

Usage: python3 feature_extract_incremental.py
"""
import json
import os
import sys
import warnings

import numpy as np

from weighted_compact.feature_extract import (
    BATCH_SIZE,
    EMBED_DIM,
    MAX_CHARS,
    OUT_PATH,
    PAIRS_PATH,
    _has_cuda,
    find_premise_minus1,
    load_session_events,
)


def main():
    if not os.path.exists(OUT_PATH):
        print(f"ERROR: {OUT_PATH} not found — run feature_extract.py first")
        sys.exit(1)

    existing = np.load(OUT_PATH, allow_pickle=True)
    existing_pair_indices = set(int(x) for x in existing['pair_indices'])
    print(f"Existing features: {existing['windows'].shape}, "
          f"unique pair_indices: {len(existing_pair_indices)}")

    pairs_by_idx = {}
    with open(PAIRS_PATH, encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            pairs_by_idx[idx] = json.loads(line)

    new_idxs = sorted(i for i in pairs_by_idx if i not in existing_pair_indices)
    if not new_idxs:
        print("No new pairs to embed.")
        return

    print(f"New pairs to embed: {len(new_idxs)}  (idx range {new_idxs[0]}..{new_idxs[-1]})")

    triples = []
    meta_idxs = []
    skipped = 0
    session_cache = {}

    for pair_idx in new_idxs:
        pair = pairs_by_idx[pair_idx]
        session_id = pair.get("session_id")

        if session_id not in session_cache:
            session_cache[session_id] = load_session_events(session_id)
        events = session_cache[session_id]
        if events is None:
            warnings.warn(f"session {session_id} not found — skip pair_idx={pair_idx}")
            skipped += 1
            continue

        premise_uuid = pair.get("premise_uuid", "")
        prev_text, found = find_premise_minus1(events, premise_uuid)
        if not found:
            warnings.warn(f"premise_uuid {premise_uuid} not found in session {session_id} — skip pair_idx={pair_idx}")
            skipped += 1
            continue

        premise_text    = (pair.get("premise_text") or "")[:MAX_CHARS]
        correction_text = (pair.get("correction_text") or "")[:MAX_CHARS]
        prev_text       = (prev_text or "")[:MAX_CHARS]

        triples.append((prev_text, premise_text, correction_text))
        meta_idxs.append(pair_idx)

    if not triples:
        print("No embeddable triples (all skipped).")
        return

    flat_texts = []
    for t1, t2, t3 in triples:
        flat_texts.append("passage: " + t1 if t1 else "")
        flat_texts.append("passage: " + t2 if t2 else "")
        flat_texts.append("passage: " + t3 if t3 else "")

    print("Loading multilingual-e5-small ...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("intfloat/multilingual-e5-small")

    device = "cuda" if _has_cuda() else "cpu"
    print(f"Embedding {len(flat_texts)} texts on {device} (batch={BATCH_SIZE}) ...")

    non_empty_idx  = [i for i, t in enumerate(flat_texts) if t]
    non_empty_texts = [flat_texts[i] for i in non_empty_idx]

    new_vecs = np.zeros((len(flat_texts), EMBED_DIM), dtype=np.float32)
    if non_empty_texts:
        vecs = model.encode(
            non_empty_texts,
            device=device,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        for i, src_i in enumerate(non_empty_idx):
            new_vecs[src_i] = vecs[i]

    N = len(triples)
    new_windows = new_vecs.reshape(N, 3, EMBED_DIM)
    new_pair_idxs   = np.array(meta_idxs, dtype=np.int32)
    new_labels_3t   = np.full(N, -1, dtype=np.int8)   # sentinel: unlabeled
    new_confidence  = np.array([b"fresh"]   * N, dtype="|S8")
    new_labeled_by  = np.array([b"pending"] * N, dtype="|S16")

    merged = {
        "windows":      np.concatenate([existing["windows"],      new_windows],     axis=0),
        "labels_3tier": np.concatenate([existing["labels_3tier"], new_labels_3t],   axis=0),
        "pair_indices": np.concatenate([existing["pair_indices"], new_pair_idxs],   axis=0),
        "confidence":   np.concatenate([existing["confidence"],   new_confidence],  axis=0),
        "labeled_by":   np.concatenate([existing["labeled_by"],   new_labeled_by],  axis=0),
    }
    np.savez(OUT_PATH, **merged)

    print("\n--- Summary ---")
    print(f"Output           : {OUT_PATH}")
    print(f"windows shape    : {merged['windows'].shape}")
    print(f"Appended         : {N}  (skipped {skipped})")
    print(f"New pair_indices : {meta_idxs}")


if __name__ == "__main__":
    main()
