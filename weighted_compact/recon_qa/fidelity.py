"""Reconstruction-QA eval loop + qa_set journal accessors.

Black box:
  вход — k_drop, ranker, topic_decay (defaults preserve old behavior).
  выход — list of result dicts per QA entry: {predicted, substring_pass, judge,
          context_chars} merged with the entry. Persists nothing — caller
          owns the journal.
  как открыт — `run_eval` is the entry point; iterates over `load_qa_set()`
          and calls `build_compacted_context` → `ask_ollama` → `score` +
          `llm_judge`. qa_set helpers (load/used/sample/save_qa_entry) live
          here as the natural neighbours of run_eval.

This module is the orchestrator: it imports from context/generator/judge and
glues them together. The four black boxes themselves are pure.
"""
import datetime
import json
import random
from collections import Counter

from ._constants import JUDGE_MODEL, RECON_SET
from .context import (
    build_compacted_context,
    load_density,
    load_importance,
    load_pairs,
    load_topic_map,
)
from .generator import ask_ollama
from .judge import llm_judge, score


def load_qa_set():
    """Read recon_qa_set.jsonl, return list of entry dicts.

    Tolerant to corrupted lines: this file is human-readable and frequently
    edited by hand, so an unterminated last line or a saved-while-writing
    partial record must not blow up downstream eval.
    """
    if not RECON_SET.exists():
        return []
    out = []
    with open(RECON_SET, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def used_pair_idxs():
    return {e['source_pair_idx'] for e in load_qa_set()}


def sample_for_build(pairs, used_idxs):
    """Pick a random pair_idx not in used_idxs, prefer sessions with >=3 pairs."""
    session_sizes = Counter(p['session_id'] for p in pairs)
    candidates = [
        p for p in pairs
        if p['pair_idx'] not in used_idxs
        and session_sizes[p['session_id']] >= 3
    ]
    if not candidates:
        return None
    return random.choice(candidates)


def save_qa_entry(entry):
    """Append entry to recon_qa_set.jsonl; created_at stamped here."""
    entry['created_at'] = datetime.datetime.now().isoformat()
    with open(RECON_SET, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def run_eval(k_drop=0.5, ranker='importance', topic_decay=0.5):
    """Evaluate all Q&A entries: build context, query ollama, score with substring + LLM judge.

    ranker: 'importance' (Phase 4C mixture, default) or 'density' (legacy).
    topic_decay: float ∈ (0, 1]. 1.0 = disabled; 0.5 = halve per topic step;
        0.0 = drop everything outside current topic.
    """
    pairs = load_pairs()
    scores = load_importance() if ranker == 'importance' else load_density()
    topic_map = load_topic_map() if topic_decay < 1.0 else None
    qa_set = load_qa_set()
    results = []
    for entry in qa_set:
        ctx = build_compacted_context(
            entry['source_pair_idx'], pairs, scores, k_drop,
            topic_decay=topic_decay, topic_map=topic_map,
        )
        if not ctx:
            results.append({
                **entry,
                'predicted': '<empty_context>',
                'substring_pass': False,
                'judge': {'verdict': 'no', 'reasoning': 'empty context', 'model': JUDGE_MODEL},
                'context_chars': 0,
            })
            continue
        pred = ask_ollama(ctx, entry['q'])
        sub_pass = score(pred, entry['a_truth'])
        src_pair = (
            pairs[entry['source_pair_idx']]
            if 0 <= entry['source_pair_idx'] < len(pairs)
            else None
        )
        judge = llm_judge(entry['q'], entry['a_truth'], pred, source_pair=src_pair)
        results.append({
            **entry,
            'predicted': pred,
            'substring_pass': sub_pass,
            'judge': judge,
            'context_chars': len(ctx),
        })
    return results
