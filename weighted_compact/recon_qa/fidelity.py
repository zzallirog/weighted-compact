"""Reconstruction-QA eval loop + qa_set journal accessors.

Black box:
  input — k_drop, ranker, topic_decay (defaults preserve old behavior).
  output — list of result dicts per QA entry: {predicted, substring_pass, judge,
          context_chars} merged with the entry. Persists nothing — caller
          owns the journal.
  entry — `run_eval` is the entry point; iterates over `load_qa_set()`
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
    load_baseline_random,
    load_baseline_recency,
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


def _load_cosine_ranker():
    """Lazy: import only when cosine is requested (pulls sentence-transformers)."""
    from weighted_compact.baselines.cosine_ranker import CosineRanker
    return CosineRanker()


def _load_bm25_ranker():
    """Lazy: import only when bm25 is requested (pulls rank-bm25)."""
    from weighted_compact.baselines.bm25_ranker import Bm25Ranker
    return Bm25Ranker()


def _load_compact_qwen():
    """Lazy: local Ollama qwen2.5:7b summarizer."""
    from weighted_compact.baselines.compact_simulator import build_qwen
    return build_qwen()


def _load_compact_sonnet():
    """Lazy: Anthropic API Sonnet summarizer (requires ANTHROPIC_API_KEY)."""
    from weighted_compact.baselines.compact_simulator import build_sonnet
    return build_sonnet()


_RANKER_LOADERS = {
    'importance': load_importance,
    'density': load_density,
    'random': load_baseline_random,
    'recency': load_baseline_recency,
    'cosine': _load_cosine_ranker,
    'bm25': _load_bm25_ranker,
    'compact_qwen': _load_compact_qwen,
    'compact_sonnet': _load_compact_sonnet,
}


def run_eval(k_drop=0.5, ranker='importance', topic_decay=0.5):
    """Evaluate all Q&A entries: build context, query ollama, score with substring + LLM judge.

    ranker: one of the registered ranker names —
        - 'importance' (Phase 4C mixture, default static)
        - 'density' (legacy fallback static)
        - 'random' / 'recency' (Phase 1 baseline static)
        - 'cosine' / 'bm25' (Phase 2 baseline, query-aware — context
          per Q rather than fixed per source_pair)
        New rankers register by adding to `_RANKER_LOADERS`.
    topic_decay: float ∈ (0, 1]. 1.0 = disabled; 0.5 = halve per topic step;
        0.0 = drop everything outside current topic.

    Fairness note: static rankers see same context for all Qs under a
    source_pair; query-aware rankers see per-Q context. This asymmetry
    is the paradigm comparison the baseline table exposes.
    """
    pairs = load_pairs()
    loader = _RANKER_LOADERS.get(ranker)
    if loader is None:
        raise ValueError(
            f'unknown ranker {ranker!r}; '
            f'known: {sorted(_RANKER_LOADERS)}',
        )
    scoring = loader()  # dict (static), callable (query-aware), or summarizer
    is_compact_bypass = getattr(scoring, 'is_compact_bypass', False)
    topic_map = load_topic_map() if (topic_decay < 1.0 and not is_compact_bypass) else None
    qa_set = load_qa_set()
    results = []
    for entry in qa_set:
        if is_compact_bypass:
            # /compact-style: bypass pair selection, replace context with
            # full-history LLM summary. k_drop and topic_decay are ignored
            # — the summary IS the context.
            ctx = scoring.summarize_excluding(
                entry['source_pair_idx'], pairs, query=entry.get('q'),
            )
        else:
            ctx = build_compacted_context(
                entry['source_pair_idx'], pairs, scoring, k_drop,
                topic_decay=topic_decay, topic_map=topic_map,
                query=entry.get('q'),
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
