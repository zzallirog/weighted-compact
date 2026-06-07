#!/usr/bin/env python3
"""Phase 2: extract 3-turn windows + e5 embeddings for classifier training."""
import json
import os
import sys
import warnings

import numpy as np

from weighted_compact import config
from weighted_compact.config import SKIP_PREFIXES

LABELS_PATH = str(config.labels_path())
PAIRS_PATH = str(config.pairs_path())
OUT_PATH = str(config.features_path())
SESSION_DIRS = [str(p) for p in config.claude_source_dirs()]
EMBED_DIM = 384
BATCH_SIZE = 64
MAX_CHARS = 480  # ~512 tokens for RU text

LABEL_MAP = {"keep": 2, "maybe": 1, "skip": 0, "false_positive": 0}


def extract_text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text", "").strip()
                if t:
                    texts.append(t)
        return "\n".join(texts).strip()
    return ""


def is_real_text(text, role):
    if not text:
        return False
    if any(text.startswith(p) for p in SKIP_PREFIXES):
        return False
    if role == "user":
        return 3 <= len(text) <= 4000
    if role == "assistant":
        return len(text) >= 20
    return False


def load_session_events(session_id):
    """Load filtered event sequence from session jsonl. Returns list of dicts."""
    import glob as _glob
    candidates = []
    for d in SESSION_DIRS:
        candidates.append(os.path.join(d, session_id + ".jsonl"))
        candidates.extend(_glob.glob(os.path.join(d, "*", session_id + ".jsonl")))
    for path in candidates:
        if not os.path.exists(path):
            continue
        events = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = obj.get("type")
                if role not in ("user", "assistant"):
                    continue
                msg = obj.get("message") or {}
                text = extract_text(msg.get("content", ""))
                if not is_real_text(text, role):
                    continue
                events.append({
                    "role": role,
                    "uuid": obj.get("uuid", ""),
                    "text": text,
                })
        return events
    return None


def find_premise_minus1(events, premise_uuid):
    """Return text of nearest prior assistant event before premise position."""
    premise_pos = None
    for i, ev in enumerate(events):
        if ev["uuid"] == premise_uuid:
            premise_pos = i
            break
    if premise_pos is None:
        return None, False  # uuid not found
    for i in range(premise_pos - 1, -1, -1):
        if events[i]["role"] == "assistant":
            return events[i]["text"], True
    return "", True  # head of session — empty string


def main(all_pairs: bool | None = None):
    # all_pairs builds the *query* substrate (every pair embedded, for
    # search_pairs / compact_session over the whole corpus). Without it the
    # default is the *training* substrate: only labeled pairs, for the
    # classifier. The MCP tools want full coverage, so bootstrap passes it.
    # Param wins; falling back to the CLI flag keeps `python -m … --all-pairs`
    # working when invoked directly.
    all_pairs_mode = all_pairs if all_pairs is not None else ("--all-pairs" in sys.argv)
    # Load all pairs indexed by pair_idx
    pairs_by_idx = {}
    with open(PAIRS_PATH, encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                pairs_by_idx[idx] = json.loads(line)
            except json.JSONDecodeError:
                pass

    # Load labels
    labels = []
    with open(LABELS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                labels.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Build triples.
    #   default mode     → iterate labeled pairs (classifier-training features)
    #   --all-pairs mode → iterate every pair (query substrate); labels become an
    #                      optional overlay keyed by (session_id, pair_idx) so a
    #                      rebuilt pairs.jsonl cannot mis-attach a drifted label,
    #                      and pairs with a missing session still embed
    #                      premise+correction (zero prev window) instead of being
    #                      dropped.
    triples = []       # list of (prev_assistant, premise, correction)
    meta    = []       # list of (pair_idx, label_int, confidence_bytes, labeled_by_bytes)
    skipped = 0
    session_cache = {}

    if all_pairs_mode:
        label_by_key = {}
        for entry in labels:
            try:
                label_by_key[(entry.get("session_id"), int(entry["pair_idx"]))] = entry
            except (KeyError, ValueError, TypeError):
                continue
        work_items = [
            (pidx, pairs_by_idx[pidx], label_by_key.get((pairs_by_idx[pidx].get("session_id"), pidx)))
            for pidx in sorted(pairs_by_idx)
        ]
    else:
        work_items = [
            (int(e["pair_idx"]), pairs_by_idx.get(int(e["pair_idx"])), e)
            for e in labels if "pair_idx" in e
        ]

    for pair_idx, pair, entry in work_items:
        if pair is None:
            warnings.warn(f"WARN: pair_idx={pair_idx} not in pairs.jsonl — skip")
            skipped += 1
            continue

        label_str  = entry.get("label", "skip") if entry else "skip"
        labeled_by = (entry.get("labeled_by", "user") if entry else "none")
        confidence = entry.get("confidence", "gold") if (entry and labeled_by != "user") else "gold"
        label_int  = LABEL_MAP.get(label_str, 0)

        session_id = (entry.get("session_id") if entry else None) or pair.get("session_id")
        if session_id not in session_cache:
            session_cache[session_id] = load_session_events(session_id)
        events = session_cache[session_id]

        prev_text = ""
        if events is None:
            if not all_pairs_mode:
                warnings.warn(f"WARN: session {session_id} not found — skip pair_idx={pair_idx}")
                skipped += 1
                continue
        else:
            premise_uuid = pair.get("premise_uuid", "")
            pt, found = find_premise_minus1(events, premise_uuid)
            if found:
                prev_text = pt or ""
            elif not all_pairs_mode:
                warnings.warn(f"WARN: premise_uuid {premise_uuid} not found in session {session_id} — skip pair_idx={pair_idx}")
                skipped += 1
                continue

        premise_text    = (pair.get("premise_text") or "")[:MAX_CHARS]
        correction_text = (pair.get("correction_text") or "")[:MAX_CHARS]
        prev_text       = (prev_text or "")[:MAX_CHARS]

        triples.append((prev_text, premise_text, correction_text))
        meta.append((pair_idx, label_int, confidence.encode()[:8], labeled_by.encode()[:16]))

    if not triples:
        print("ERROR: no valid triples extracted")
        sys.exit(1)

    # Flatten all texts for batched embedding
    flat_texts = []
    for t1, t2, t3 in triples:
        flat_texts.append("passage: " + t1 if t1 else "")
        flat_texts.append("passage: " + t2 if t2 else "")
        flat_texts.append("passage: " + t3 if t3 else "")

    # Lazy import: e5 embeddings are the [baselines] tier, not core. Importing
    # at module top would make `bootstrap --full` die on a [mcp]-only install
    # before it can build the (embedding-free) compaction substrate.
    from sentence_transformers import SentenceTransformer

    print("Loading multilingual-e5-small ...")
    model = SentenceTransformer("intfloat/multilingual-e5-small")

    device = "cuda" if _has_cuda() else "cpu"
    print(f"Embedding {len(flat_texts)} texts on {device} (batch={BATCH_SIZE}) ...")

    # Embed non-empty texts; keep zero vectors for empty strings
    non_empty_idx  = [i for i, t in enumerate(flat_texts) if t]
    non_empty_texts = [flat_texts[i] for i in non_empty_idx]

    all_vecs = np.zeros((len(flat_texts), EMBED_DIM), dtype=np.float32)
    if non_empty_texts:
        vecs = model.encode(
            non_empty_texts,
            device=device,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        for i, src_i in enumerate(non_empty_idx):
            all_vecs[src_i] = vecs[i]

    N = len(triples)
    windows    = all_vecs.reshape(N, 3, EMBED_DIM)
    pair_idxs  = np.array([m[0] for m in meta], dtype=np.int32)
    labels_3t  = np.array([m[1] for m in meta], dtype=np.int8)
    confidence = np.array([m[2] for m in meta], dtype="|S8")
    labeled_by = np.array([m[3] for m in meta], dtype="|S16")

    np.savez(
        OUT_PATH,
        windows=windows,
        labels_3tier=labels_3t,
        pair_indices=pair_idxs,
        confidence=confidence,
        labeled_by=labeled_by,
    )

    # Summary
    label_dist = {v: int(np.sum(labels_3t == k)) for k, v in [(0, "drop"), (1, "maybe"), (2, "keep")]}
    print("\n--- Summary ---")
    print(f"Output           : {OUT_PATH}")
    print(f"windows shape    : {windows.shape}")
    print(f"labels_3tier     : {labels_3t.shape}  dist={label_dist}")
    print(f"pair_indices     : {pair_idxs.shape}")
    print(f"confidence       : {confidence.shape}")
    print(f"labeled_by       : {labeled_by.shape}")
    print(f"Successful       : {N}")
    print(f"Skipped          : {skipped}")
    print(f"Total labels     : {N + skipped}")


def _has_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


if __name__ == "__main__":
    main()
